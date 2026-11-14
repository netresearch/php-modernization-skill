<?php

declare(strict_types=1);

namespace Cases\EnumOrderStatus;

final class OrderLabel
{
    public function label(OrderStatus $status): string
    {
        return match ($status) {
            OrderStatus::Pending => 'Awaiting payment',
            OrderStatus::Paid => 'Paid',
            OrderStatus::Shipped => 'Shipped',
        };
    }
}
