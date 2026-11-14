<?php

declare(strict_types=1);

namespace Cases\UnknownStoredShipment;

enum ShipmentStatus: string
{
    case InTransit = 'in_transit';
    case Delivered = 'delivered';
}
