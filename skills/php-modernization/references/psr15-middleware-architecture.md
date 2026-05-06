# PSR-15 Middleware Architecture

PSR-15 (https://www.php-fig.org/psr/psr-15/) defines two interfaces — `RequestHandlerInterface` and `MiddlewareInterface` — that frame how HTTP request processing is composed. This reference covers the architectural patterns that make PSR-15 stacks modernizable, testable, and analyzable.

> **Source of truth:** https://www.php-fig.org/psr/psr-15/
> PSR-15 builds on PSR-7 (HTTP messages) and PSR-17 (factories). See `references/psr-per-compliance.md` for the full PSR family.

## The two interfaces

PSR-15 specifies exactly two contracts. Both live under `Psr\Http\Server\`.

```php
namespace Psr\Http\Server;

use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;

interface RequestHandlerInterface
{
    /**
     * Handles a request and produces a response.
     */
    public function handle(ServerRequestInterface $request): ResponseInterface;
}

interface MiddlewareInterface
{
    /**
     * Process an incoming server request.
     *
     * Processes an incoming server request in order to produce a response.
     * If unable to produce the response itself, it may delegate to the
     * provided request handler to do so.
     */
    public function process(
        ServerRequestInterface $request,
        RequestHandlerInterface $handler,
    ): ResponseInterface;
}
```

A handler terminates the chain — it returns a response. A middleware sits in front of a handler — it may short-circuit (return its own response) or delegate (call `$handler->handle($request)`).

## The middleware pipeline

Middleware composes by nesting. Each middleware receives a handler representing "the rest of the stack" and chooses whether to call it. A controller is the innermost handler.

```php
<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;
use Psr\Http\Server\MiddlewareInterface;
use Psr\Http\Server\RequestHandlerInterface;

final readonly class ExceptionToResponseMiddleware implements MiddlewareInterface
{
    public function __construct(private ResponseFactoryInterface $responses) {}

    public function process(
        ServerRequestInterface $request,
        RequestHandlerInterface $handler,
    ): ResponseInterface {
        try {
            return $handler->handle($request);
        } catch (DomainException $e) {
            return $this->responses->problem(422, $e->getMessage());
        } catch (\Throwable $e) {
            return $this->responses->problem(500, 'Internal Server Error');
        }
    }
}

final readonly class AuthMiddleware implements MiddlewareInterface
{
    public function __construct(private TokenVerifier $tokens) {}

    public function process(
        ServerRequestInterface $request,
        RequestHandlerInterface $handler,
    ): ResponseInterface {
        $user = $this->tokens->verify($request->getHeaderLine('Authorization'));

        return $handler->handle($request->withAttribute('user', $user));
    }
}

final readonly class LoggingMiddleware implements MiddlewareInterface
{
    public function __construct(private LoggerInterface $logger) {}

    public function process(
        ServerRequestInterface $request,
        RequestHandlerInterface $handler,
    ): ResponseInterface {
        $start = hrtime(true);
        $response = $handler->handle($request);
        $this->logger->info('http.request', [
            'method'   => $request->getMethod(),
            'path'     => $request->getUri()->getPath(),
            'status'   => $response->getStatusCode(),
            'duration' => (hrtime(true) - $start) / 1e6,
        ]);

        return $response;
    }
}

final readonly class CreateOrderHandler implements RequestHandlerInterface
{
    public function __construct(private CreateOrderUseCase $useCase) {}

    public function handle(ServerRequestInterface $request): ResponseInterface
    {
        $dto = CreateOrderRequest::fromHttp($request);
        $result = $this->useCase->execute($dto);

        return JsonResponse::ok($result);
    }
}
```

Pipeline order — outer to inner — is `Exception -> Auth -> Logging -> CreateOrderHandler`. The outer middleware sees both the request before and the response after the inner stack:

```
request  ─► Exception ─► Auth ─► Logging ─► Handler
                                              │
response ◄─ Exception ◄─ Auth ◄─ Logging ◄────┘
```

Exception sees every thrown error. Auth attaches the user before downstream code runs. Logging measures total inner duration. The handler runs last and returns a response.

## Architectural rules

These rules are explicit, actionable, and PHPat-checkable.

- **Thin handlers.** A handler translates HTTP to use-case input, dispatches one use-case, and translates the result back. No business logic, no validation rules, no persistence.
- **DTO hydration at the boundary.** The handler turns `ServerRequestInterface` into a typed Request DTO before any domain code runs. See `references/request-dtos.md`.
- **Cross-cutting concerns are middleware, never the handler** — auth, rate limiting, CSRF, content negotiation, logging, telemetry, correlation IDs, transaction boundaries.
- **Exception-to-response middleware is outermost.** It must be first in the chain so it catches everything below — including failures inside other middleware.
- **No infrastructure leakage.** Middleware and handlers depend only on PSR types and use-case ports. No Doctrine entities, no PDO, no Symfony container, no framework-specific request objects.
- **Middleware order is explicit, declarative configuration** — a list in a config file or a compiled pipeline. Never implicit by registration order or runtime mutation.
- **Final classes for handlers and middleware** (no inheritance). Use `readonly` when the class has only injected dependencies.

## Anti-patterns

```php
// Anti-pattern 1: Fat controller handler with business logic.
final class CreateOrderHandler implements RequestHandlerInterface
{
    public function handle(ServerRequestInterface $request): ResponseInterface
    {
        $body = $request->getParsedBody();
        if (!is_array($body) || empty($body['items'])) {                    // BAD: validation here
            return new JsonResponse(['error' => 'invalid'], 400);
        }
        $total = 0;
        foreach ($body['items'] as $item) {                                 // BAD: business logic here
            $total += $item['price'] * $item['qty'];
        }
        $stmt = $this->pdo->prepare('INSERT INTO orders ...');              // BAD: persistence here
        $stmt->execute([$total]);

        return new JsonResponse(['id' => $this->pdo->lastInsertId()]);
    }
}
```

```php
// Anti-pattern 2: Middleware doing business logic.
final class PricingMiddleware implements MiddlewareInterface
{
    public function process(ServerRequestInterface $request, RequestHandlerInterface $handler): ResponseInterface
    {
        $items = $request->getParsedBody()['items'] ?? [];
        $total = $this->calculator->total($items);   // BAD: domain calculation in middleware
        return $handler->handle($request->withAttribute('total', $total));
    }
}
```

```php
// Anti-pattern 3: Implicit ordering via ad-hoc registration.
$pipeline = [];
$pipeline[] = new LoggingMiddleware(...);
array_unshift($pipeline, new AuthMiddleware(...));   // BAD: order depends on call sequence
```

```php
// Anti-pattern 4: Handler swallowing its own exceptions.
public function handle(ServerRequestInterface $request): ResponseInterface
{
    try {
        return JsonResponse::ok($this->useCase->execute(...));
    } catch (\Throwable $e) {                        // BAD: belongs in ExceptionToResponseMiddleware
        return new JsonResponse(['error' => $e->getMessage()], 500);
    }
}
```

```php
// Anti-pattern 5: Middleware constructing DTOs.
final class HydrateOrderMiddleware implements MiddlewareInterface
{
    public function process(ServerRequestInterface $request, RequestHandlerInterface $handler): ResponseInterface
    {
        $dto = CreateOrderRequest::fromHttp($request);    // BAD: DTO hydration is the handler's job
        return $handler->handle($request->withAttribute('dto', $dto));
    }
}
```

## PHPat rules to enforce

These rules codify the architectural rules above. Syntax follows the convention in `references/static-analysis-tools.md` (https://github.com/carlosas/phpat).

```php
<?php

declare(strict_types=1);

namespace Tests\Architecture;

use PHPat\Selector\Selector;
use PHPat\Test\Builder\Rule;
use PHPat\Test\PHPat;
use Psr\Http\Server\MiddlewareInterface;
use Psr\Http\Server\RequestHandlerInterface;

final class Psr15ArchitectureTest
{
    /** All *Middleware classes implement MiddlewareInterface. */
    public function testMiddlewareImplementsContract(): Rule
    {
        return PHPat::rule()
            ->classes(Selector::classname('*Middleware'))
            ->shouldImplement()
            ->classes(Selector::classname(MiddlewareInterface::class));
    }

    /** All *Handler / *Action classes implement RequestHandlerInterface. */
    public function testHandlersImplementContract(): Rule
    {
        return PHPat::rule()
            ->classes(
                Selector::classname('*Handler'),
                Selector::classname('*Action'),
            )
            ->shouldImplement()
            ->classes(Selector::classname(RequestHandlerInterface::class));
    }

    /** Handlers must not depend on Doctrine ORM. */
    public function testHandlersNoDoctrine(): Rule
    {
        return PHPat::rule()
            ->classes(Selector::inNamespace('App\Http\Handler'))
            ->shouldNotDependOn()
            ->classes(Selector::inNamespace('Doctrine\ORM'))
            ->because('Handlers depend on use-case ports, not persistence');
    }

    /** Middleware must not depend on application use-case namespace. */
    public function testMiddlewareNoUseCases(): Rule
    {
        return PHPat::rule()
            ->classes(Selector::inNamespace('App\Http\Middleware'))
            ->shouldNotDependOn()
            ->classes(Selector::inNamespace('App\UseCase'))
            ->because('Middleware is for cross-cutting concerns, not business logic');
    }

    /** Handlers and middleware must be final. */
    public function testHttpClassesAreFinal(): Rule
    {
        return PHPat::rule()
            ->classes(
                Selector::classname('*Handler'),
                Selector::classname('*Middleware'),
            )
            ->shouldBeFinal();
    }
}
```

## Integration with frameworks

- **Symfony.** Symfony's HttpKernel is not PSR-15 native. Use `symfony/psr-http-message-bridge` plus a PSR-15 dispatcher to run PSR-15 stacks inside Symfony, or run PSR-15 as a standalone HTTP front layer in front of the kernel. See `references/symfony-patterns.md`.
- **TYPO3.** TYPO3 v10+ middleware is PSR-15 native — register middleware in `Configuration/RequestMiddlewares.php` with explicit `before` / `after` ordering. TYPO3-specific PSR patterns live in the `typo3-conformance` skill (see checkpoints TC-180 PSR-3 logging and TC-181 PSR-14 events).
- **Slim / Mezzio.** Both are PSR-15 native. Mezzio in particular is the reference PSR-15 framework — its `MiddlewarePipe` is the canonical pipeline implementation.

## Verification and testing

- Each middleware is unit-testable in isolation: instantiate, call `process()` with a mock `ServerRequestInterface` plus a mock `RequestHandlerInterface`, assert the returned response and the calls made on the inner handler.
- Pipeline integration tests run the real middleware against real handlers with real PSR-7 messages built via `laminas/laminas-diactoros` or `nyholm/psr7` (PSR-17 factories).
- PHPat enforces the architecture rules above in CI — fail the build, not the review.
- PHPStan with `level: max` and `treatPhpDocTypesAsCertain: false` catches type drift across the boundary.
- Mutation testing (Infection) on middleware and handlers — they are small, pure, and high-leverage.

## Migration patterns

To migrate from a "fat controller + framework filters" stack to PSR-15:

1. **Extract cross-cutting concerns into middleware classes.** Auth filter -> `AuthMiddleware`. Exception handler -> `ExceptionToResponseMiddleware`. Logger interceptor -> `LoggingMiddleware`. Each implements `MiddlewareInterface`.
2. **Introduce a Request DTO boundary.** For each endpoint, build a `*Request` DTO with a `fromHttp(ServerRequestInterface)` named constructor that performs validation. See `references/request-dtos.md`.
3. **Split controller logic into use-case + handler.** Pure business logic moves into a `*UseCase` class with a typed input DTO and a typed output DTO. The HTTP handler becomes a thin adapter.
4. **Wire as a PSR-15 pipeline.** Declare the middleware order in configuration. Outermost first: `Exception -> Auth -> RateLimit -> Logging -> Handler`.
5. **Add PHPat rules to lock in the architecture.** Once the migration lands, the rules above prevent regression.
