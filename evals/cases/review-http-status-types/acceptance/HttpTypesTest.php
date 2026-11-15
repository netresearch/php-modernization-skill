<?php

declare(strict_types=1);

namespace Acme\HttpStatus\Tests\Acceptance;

use Acme\HttpStatus\Request;
use Acme\HttpStatus\Response;
use Acme\HttpStatus\ResponseSummary;
use Acme\HttpStatus\StatusText;
use PHPUnit\Framework\TestCase;

final class HttpTypesTest extends TestCase
{
    public function testRequestAndResponseAreTyped(): void
    {
        foreach ([Request::class, Response::class] as $class) {
            $reflection = new \ReflectionClass($class);
            foreach ($reflection->getProperties() as $property) {
                self::assertTrue($property->hasType(), "{$class}::\${$property->getName()} has no type");
            }
            foreach ($reflection->getMethods() as $method) {
                if ($method->getName() !== '__construct') {
                    self::assertTrue($method->hasReturnType(), "{$class}::{$method->getName()}() has no return type");
                }
            }
        }
    }

    public function testTheSwitchIsGone(): void
    {
        // Tokens, not text: a comment that mentions the switch is fine.
        $file = (string) (new \ReflectionClass(StatusText::class))->getFileName();
        $tokens = array_map(
            static fn (\PhpToken $token): int => $token->id,
            \PhpToken::tokenize((string) file_get_contents($file)),
        );
        self::assertNotContains(T_SWITCH, $tokens);
        self::assertContains(T_MATCH, $tokens);
    }

    public function testOtherInputsCompareAsTheSwitchDid(): void
    {
        // The start state's switch compared with ==; a cast or a strict
        // match changes these.
        $text = new StatusText();
        self::assertSame('Unknown', $text->for('200abc'));
        self::assertSame('OK', $text->for(' 200'));
        self::assertSame('Unknown', $text->for(null));
        self::assertSame(
            '404x Unknown',
            (new ResponseSummary())->describe(new Response('HTTP/1.1 404x Not Found')),
        );
    }

    public function testRequestStillWorks(): void
    {
        $request = new Request('GET', '/x', ['Accept' => 'text/html']);
        self::assertSame('GET', $request->method());
        self::assertSame('text/html', $request->header('accept'));
    }

    public function testIntegerCodes(): void
    {
        self::assertSame('OK', (new StatusText())->for(200));
        self::assertSame('Unknown', (new StatusText())->for(500));
    }

    public function testSummariesOfParsedStatusLines(): void
    {
        $summary = new ResponseSummary();
        self::assertSame('404 Not Found', $summary->describe(new Response('HTTP/1.1 404 Not Found')));
        self::assertSame('301 Moved Permanently', $summary->describe(new Response('HTTP/1.1 301 Moved Permanently')));
    }
}
