<?php

declare(strict_types=1);

namespace Cases\SwitchLooseHttp;

final class HeaderParser
{
    public function __construct(private StatusText $statusText = new StatusText())
    {
    }

    /** Reads "HTTP/1.1 404 Not Found" and returns the text for its code. */
    public function statusText(string $statusLine): string
    {
        $parts = explode(' ', $statusLine);

        return $this->statusText->for($parts[1] ?? '');
    }
}
