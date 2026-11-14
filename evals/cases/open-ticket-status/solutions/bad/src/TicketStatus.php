<?php

declare(strict_types=1);

namespace Cases\OpenTicketStatus;

enum TicketStatus: string
{
    case Open = 'open';
    case Closed = 'closed';
}
