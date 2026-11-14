<?php

declare(strict_types=1);

namespace Cases\SwitchLooseHttp;

final class StatusText
{
    public function for($code): string
    {
        $text = match ($code) {
            200 => 'OK',
            404 => 'Not Found',
            default => 'Unknown',
        };
        return $text;
    }
}
