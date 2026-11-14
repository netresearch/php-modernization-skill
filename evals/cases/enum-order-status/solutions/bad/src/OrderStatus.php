<?php

declare(strict_types=1);

namespace Cases\EnumOrderStatus;

enum OrderStatus: string
{
    case Pending = 'pending';
    case Paid = 'paid';
    case Shipped = 'shipped';
}
