<?php

declare(strict_types=1);

namespace Cases\ReviewHttpStatusTypes;

final class Request
{
    /** @var array<string, string> */
    private array $headers;

    /** @param array<string, string> $headers */
    public function __construct(
        private string $method,
        private string $path,
        array $headers = [],
    ) {
        $this->headers = array_change_key_case($headers);
    }

    public function method(): string
    {
        return $this->method;
    }

    public function path(): string
    {
        return $this->path;
    }

    public function header(string $name): ?string
    {
        return $this->headers[strtolower($name)] ?? null;
    }
}
