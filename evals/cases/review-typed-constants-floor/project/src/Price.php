<?php

declare(strict_types=1);

namespace Cases\ReviewTypedConstantsFloor;

final class Price
{
    const CURRENCY = 'EUR';

    /** @var int */
    private $cents;

    /** @param int $cents */
    public function __construct($cents)
    {
        $this->cents = $cents;
    }

    public function cents(): int
    {
        return $this->cents;
    }

    public function format(): string
    {
        return number_format($this->cents / 100, 2) . ' ' . self::CURRENCY;
    }
}
