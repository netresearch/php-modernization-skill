<?php

declare(strict_types=1);

namespace Acme\Shipping;

final class Shipment
{
    public function __construct(private ?ShipmentStatus $status)
    {
    }

    /** @param array{status: string} $row */
    public static function fromRow(array $row): self
    {
        return new self(ShipmentStatus::from($row['status']));
    }

    public function status(): ?ShipmentStatus
    {
        return $this->status;
    }

    public function label(): string
    {
        return match ($this->status) {
            ShipmentStatus::InTransit => 'In transit',
            ShipmentStatus::Delivered => 'Delivered',
            null => 'Unknown',
        };
    }
}
