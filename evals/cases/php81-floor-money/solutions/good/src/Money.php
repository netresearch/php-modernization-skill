<?php

declare(strict_types=1);

namespace Cases\Php81FloorMoney;

final class Money
{
    // readonly properties (PHP 8.1), not a readonly class (PHP 8.2): the
    // package still supports PHP 8.1.
    public function __construct(
        private readonly int $amount,
        private readonly string $currency,
    ) {
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
