<?php

declare(strict_types=1);

namespace Acme\HttpLabels;

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
