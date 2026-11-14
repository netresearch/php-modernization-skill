<?php

declare(strict_types=1);

namespace Cases\ReviewHttpStatusTypes;

final class Response
{
    /** @var string */
    private $statusLine;
    /** @var string */
    private $body;

    /**
     * @param string $statusLine
     * @param string $body
     */
    public function __construct($statusLine, $body = '')
    {
        $this->statusLine = $statusLine;
        $this->body = $body;
    }

    /** @return string */
    public function statusLine()
    {
        return $this->statusLine;
    }

    /** @return string */
    public function body()
    {
        return $this->body;
    }
}
