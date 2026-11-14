<?php

declare(strict_types=1);

namespace Cases\SwitchLooseHttp;

final class StatusText
{
    /**
     * Header parsing passes the code as a string. Casting to int keeps the
     * loose comparison the callers relied on; a strict match on the raw value
     * would send "200" to the default arm.
     */
    public function for(int|string $code): string
    {
        return match ((int) $code) {
            200 => 'OK',
            404 => 'Not Found',
            default => 'Unknown',
        };
    }
}
