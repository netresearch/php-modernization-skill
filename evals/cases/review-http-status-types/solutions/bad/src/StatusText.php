<?php

declare(strict_types=1);

namespace Cases\ReviewHttpStatusTypes;

final class StatusText
{
    public function for(int $code): string
    {
        return match ($code) {
            200 => 'OK',
            301 => 'Moved Permanently',
            404 => 'Not Found',
            default => 'Unknown',
        };
    }
}
