<?php

declare(strict_types=1);

namespace Cases\ReviewInvoiceEnumData;

final class Invoice
{
    public function __construct(private string $id, private ?InvoiceStatus $status, private int $total)
    {
    }

    public function id(): string
    {
        return $this->id;
    }

    public function status(): ?InvoiceStatus
    {
        return $this->status;
    }

    public function total(): int
    {
        return $this->total;
    }
}
