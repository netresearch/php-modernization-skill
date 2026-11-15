<?php

declare(strict_types=1);

namespace Acme\ShopOrders;

final class OrderLabel
{
    public function label(OrderStatus $status): string
    {
        return $status->label();
    }
}
