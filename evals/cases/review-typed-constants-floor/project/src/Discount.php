<?php

declare(strict_types=1);

namespace Cases\ReviewTypedConstantsFloor;

final class Discount
{
    const MAX_PERCENT = 50;

    /** @var int */
    private $percent;

    /** @param int $percent */
    public function __construct($percent)
    {
        $this->percent = min($percent, self::MAX_PERCENT);
    }

    public function apply(Price $price): Price
    {
        return new Price(intdiv($price->cents() * (100 - $this->percent), 100));
    }
}
