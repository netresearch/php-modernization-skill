<?php

declare(strict_types=1);

namespace Acme\Invoices;

final class InvoiceLabel
{
    public function label(string $status): string
    {
        return match ($status) {
            'open' => 'Open',
            'paid' => 'Paid',
            default => 'Unknown',
        };
    }
}
