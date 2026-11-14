<?php

declare(strict_types=1);

namespace Cases\ReviewTypedConstantsFloor;

final readonly class Discount
{
    public const MAX_PERCENT = 50;

    private int $percent;

    public function __construct(int $percent)
    {
        $this->percent = min($percent, self::MAX_PERCENT);
    }

    public function apply(Price $price): Price
    {
        return new Price(intdiv($price->cents() * (100 - $this->percent), 100));
    }
}
