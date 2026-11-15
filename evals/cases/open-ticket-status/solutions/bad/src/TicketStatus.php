<?php

declare(strict_types=1);

namespace Acme\Helpdesk;

enum TicketStatus: string
{
    case Open = 'open';
    case Closed = 'closed';
}
