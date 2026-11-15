<?php

declare(strict_types=1);

namespace Acme\Shipping;

enum ShipmentStatus: string
{
    case InTransit = 'in_transit';
    case Delivered = 'delivered';
}
