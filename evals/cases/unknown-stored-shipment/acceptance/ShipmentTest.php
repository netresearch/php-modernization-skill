<?php

declare(strict_types=1);

namespace Cases\UnknownStoredShipment\Tests\Acceptance;

use Cases\UnknownStoredShipment\Shipment;
use Cases\UnknownStoredShipment\ShipmentStatus;
use PHPUnit\Framework\TestCase;

final class ShipmentTest extends TestCase
{
    public function testKnownValuesBecomeTheEnum(): void
    {
        self::assertTrue(enum_exists(ShipmentStatus::class));
        $shipment = Shipment::fromRow(['status' => 'delivered']);
        self::assertSame(ShipmentStatus::Delivered, $shipment->status());
        self::assertSame('Delivered', $shipment->label());
        self::assertSame('In transit', Shipment::fromRow(['status' => 'in_transit'])->label());
    }

    public function testLegacyRowsStillLoadAndShowUnknown(): void
    {
        $shipment = Shipment::fromRow(['status' => 'lost_in_customs']);
        self::assertNull($shipment->status());
        self::assertSame('Unknown', $shipment->label());
    }
}
