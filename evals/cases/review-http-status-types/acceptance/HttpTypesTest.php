<?php

declare(strict_types=1);

namespace Cases\ReviewHttpStatusTypes\Tests\Acceptance;

use Cases\ReviewHttpStatusTypes\Request;
use Cases\ReviewHttpStatusTypes\Response;
use Cases\ReviewHttpStatusTypes\ResponseSummary;
use Cases\ReviewHttpStatusTypes\StatusText;
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
        $source = (string) file_get_contents((new \ReflectionClass(StatusText::class))->getFileName());
        self::assertStringNotContainsString('switch', $source);
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
