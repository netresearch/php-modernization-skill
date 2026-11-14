<?php

declare(strict_types=1);

namespace Cases\ReviewTypedConstantsFloor;

final class Cart
{
    /** @var list<Price> */
    private $items = [];

    public function add(Price $price): void
    {
        $this->items[] = $price;
    }

    public function total(?Discount $discount = null): Price
    {
        $sum = new Price(array_sum(array_map(static fn (Price $p): int => $p->cents(), $this->items)));

        return $discount ? $discount->apply($sum) : $sum;
    }
}
