<?php

declare(strict_types=1);

namespace Cases\ReviewHttpStatusTypes;

final class Response
{
    public function __construct(
        private string $statusLine,
        private string $body = '',
    ) {
    }

    public function statusLine(): string
    {
        return $this->statusLine;
    }

    public function body(): string
    {
        return $this->body;
    }
}
