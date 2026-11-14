<?php

declare(strict_types=1);

namespace Cases\ReviewInvoiceEnumData;

enum InvoiceStatus: string
{
    case Open = 'open';
    case Paid = 'paid';
}
