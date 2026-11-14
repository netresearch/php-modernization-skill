<?php

declare(strict_types=1);

namespace Cases\ReviewTypedConstantsFloor;

final readonly class Price
{
    public const string CURRENCY = 'EUR';

    public function __construct(private int $cents)
    {
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
