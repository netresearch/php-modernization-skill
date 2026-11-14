<?php

declare(strict_types=1);

namespace Cases\EnumOrderStatus;

enum OrderStatus: string
{
    case PENDING = 'pending';
    case PAID = 'paid';
    case SHIPPED = 'shipped';

    public function label(): string
    {
        return match ($this) {
            self::PENDING => 'Awaiting payment',
            self::PAID => 'Paid',
            self::SHIPPED => 'Shipped',
        };
    }
}
