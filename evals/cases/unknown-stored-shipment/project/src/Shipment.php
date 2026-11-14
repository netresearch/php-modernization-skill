<?php

declare(strict_types=1);

namespace Cases\UnknownStoredShipment;

final class Shipment
{
    public function __construct(private string $status)
    {
    }

    /** @param array{status: string} $row */
    public static function fromRow(array $row): self
    {
        return new self($row['status']);
    }

    public function status(): string
    {
        return $this->status;
    }

    public function label(): string
    {
        return match ($this->status) {
            'in_transit' => 'In transit',
            'delivered' => 'Delivered',
            default => 'Unknown',
        };
    }
}
