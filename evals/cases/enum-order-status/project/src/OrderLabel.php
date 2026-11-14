<?php

declare(strict_types=1);

namespace Cases\EnumOrderStatus;

final class OrderLabel
{
    public function label(string $status): string
    {
        return match ($status) {
            'pending' => 'Awaiting payment',
            'paid' => 'Paid',
            'shipped' => 'Shipped',
            default => throw new \InvalidArgumentException('Unknown order status: ' . $status),
        };
    }
}
