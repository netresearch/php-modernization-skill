<?php

declare(strict_types=1);

namespace Cases\ReviewHttpStatusTypes;

final class StatusText
{
    public function for($code)
    {
        switch ($code) {
            case 200:
                $text = 'OK';
                break;
            case 301:
                $text = 'Moved Permanently';
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
