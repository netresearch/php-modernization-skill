<?php

declare(strict_types=1);

namespace Cases\UnknownStoredShipment;

final class Shipment
{
    public function __construct(private ?ShipmentStatus $status)
    {
    }

    /** @param array{status: string} $row */
    public static function fromRow(array $row): self
    {
        // Legacy rows carry values the enum does not know: keep loading them.
        return new self(ShipmentStatus::tryFrom($row['status']));
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
