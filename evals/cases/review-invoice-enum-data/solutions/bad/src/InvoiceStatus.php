<?php

declare(strict_types=1);

namespace Acme\Invoices;

enum InvoiceStatus: string
{
    case Open = 'open';
    case Paid = 'paid';
}
