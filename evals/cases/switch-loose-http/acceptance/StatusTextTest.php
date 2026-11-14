<?php

declare(strict_types=1);

namespace Cases\SwitchLooseHttp\Tests\Acceptance;

use Cases\SwitchLooseHttp\HeaderParser;
use Cases\SwitchLooseHttp\StatusText;
use PHPUnit\Framework\TestCase;

final class StatusTextTest extends TestCase
{
    public function testIntegerCodes(): void
    {
        self::assertSame('OK', (new StatusText())->for(200));
        self::assertSame('Not Found', (new StatusText())->for(404));
        self::assertSame('Unknown', (new StatusText())->for(500));
    }

    public function testCodesParsedFromHeadersAreStrings(): void
    {
        self::assertSame('OK', (new StatusText())->for('200'));
        self::assertSame('Not Found', (new HeaderParser())->statusText('HTTP/1.1 404 Not Found'));
        self::assertSame('Unknown', (new HeaderParser())->statusText('HTTP/1.1 503 Service Unavailable'));
    }

    public function testTheSwitchIsGone(): void
    {
        $source = (string) file_get_contents((new \ReflectionClass(StatusText::class))->getFileName());
        self::assertStringNotContainsString('switch', $source);
        self::assertStringContainsString('match', $source);
    }
}
