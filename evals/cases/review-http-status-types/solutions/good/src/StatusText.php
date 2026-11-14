<?php

declare(strict_types=1);

namespace Cases\ReviewHttpStatusTypes;

final class StatusText
{
    /**
     * mixed, as the untyped parameter before: callers pass the code as
     * parsed from a status line, and null or a bool still give a text.
     */
    public function for(mixed $code): string
    {
        // Loose comparison as before: '404' matches 404.
        return match (true) {
            $code == 200 => 'OK',
            $code == 301 => 'Moved Permanently',
            $code == 404 => 'Not Found',
            default => 'Unknown',
        };
    }
}
