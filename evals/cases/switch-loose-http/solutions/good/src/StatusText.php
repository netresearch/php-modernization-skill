<?php

declare(strict_types=1);

namespace Cases\SwitchLooseHttp;

final class StatusText
{
    public function for($code): string
    {
        // Loose comparison on purpose: header parsing passes the code as a string.
        return match (true) {
            $code == 200 => 'OK',
            $code == 404 => 'Not Found',
            default => 'Unknown',
        };
    }
}
