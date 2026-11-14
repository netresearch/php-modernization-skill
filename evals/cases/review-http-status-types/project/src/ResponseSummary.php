<?php

declare(strict_types=1);

namespace Cases\ReviewHttpStatusTypes;

final class ResponseSummary
{
    public function __construct(private StatusText $statusText = new StatusText())
    {
    }

    /** "HTTP/1.1 404 Not Found" gives "404 Not Found". */
    public function describe(Response $response): string
    {
        $parts = explode(' ', $response->statusLine());
        $code = $parts[1] ?? '';

        return $code . ' ' . $this->statusText->for($code);
    }
}
