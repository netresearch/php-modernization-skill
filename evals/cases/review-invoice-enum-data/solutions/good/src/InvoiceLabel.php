<?php

declare(strict_types=1);

namespace Cases\ReviewInvoiceEnumData;

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
