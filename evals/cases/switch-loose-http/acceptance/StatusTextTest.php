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

    public function testOtherStringsCompareAsTheSwitchDid(): void
    {
        // The switch compared with ==: ' 200' matched 200, '200abc' did not.
        // A cast such as (int) $code turns '200abc' into 200.
        self::assertSame('OK', (new StatusText())->for(' 200'));
        self::assertSame('Unknown', (new StatusText())->for('200abc'));
    }

    public function testTheSwitchIsGone(): void
    {
        $file = (string) (new \ReflectionClass(StatusText::class))->getFileName();
        $tokens = array_map(
            static fn (\PhpToken $t): int => $t->id,
            \PhpToken::tokenize((string) file_get_contents($file)),
        );
        // Tokens, not text: a comment that mentions the switch is fine.
        self::assertNotContains(T_SWITCH, $tokens);
        self::assertContains(T_MATCH, $tokens);
    }
}
