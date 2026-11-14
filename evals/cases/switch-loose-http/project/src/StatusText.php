<?php

declare(strict_types=1);

namespace Cases\SwitchLooseHttp;

final class StatusText
{
    public function for($code): string
    {
        switch ($code) {
            case 200:
                $text = 'OK';
                break;
            case 404:
                $text = 'Not Found';
                break;
            default:
                $text = 'Unknown';
                break;
        }
        return $text;
    }
}
