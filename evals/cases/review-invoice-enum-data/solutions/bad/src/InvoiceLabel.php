<?php

declare(strict_types=1);

namespace Acme\Invoices;

final class InvoiceLabel
{
    public function label(?InvoiceStatus $status): string
    {
        return match ($status) {
            InvoiceStatus::Open => 'Open',
            InvoiceStatus::Paid => 'Paid',
            null => 'Unknown',
        };
    }
}
