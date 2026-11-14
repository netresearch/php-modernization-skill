<?php

declare(strict_types=1);

namespace Cases\Php81FloorMoney;

final readonly class Money
{
    public function __construct(private int $amount, private string $currency)
    {
    }

    public function amount(): int
    {
        return $this->amount;
    }

    public function currency(): string
    {
        return $this->currency;
    }

    public function add(self $other): self
    {
        if ($other->currency !== $this->currency) {
            throw new \InvalidArgumentException('Currency mismatch');
        }
        return new self($this->amount + $other->amount, $this->currency);
    }
}
