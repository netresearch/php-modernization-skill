<?php

declare(strict_types=1);

namespace Cases\ReviewHttpStatusTypes;

final class Request
{
    /** @var string */
    private $method;
    /** @var string */
    private $path;
    /** @var array<string, string> */
    private $headers;

    /**
     * @param string $method
     * @param string $path
     * @param array<string, string> $headers
     */
    public function __construct($method, $path, array $headers = [])
    {
        $this->method = $method;
        $this->path = $path;
        $this->headers = array_change_key_case($headers);
    }

    /** @return string */
    public function method()
    {
        return $this->method;
    }

    /** @return string */
    public function path()
    {
        return $this->path;
    }

    /**
     * @param string $name
     * @return string|null
     */
    public function header($name)
    {
        return $this->headers[strtolower($name)] ?? null;
    }
}
