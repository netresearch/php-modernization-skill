<?php

declare(strict_types=1);

namespace Cases\EnumOrderStatus;

final class Order
{
    private const STATUSES = ['pending', 'paid', 'shipped'];

    public function __construct(private string $id, private string $status)
    {
        if (!in_array($status, self::STATUSES, true)) {
            throw new \InvalidArgumentException('Unknown order status: ' . $status);
        }
    }

    /** @param array{id: string, status: string} $row */
    public static function fromRow(array $row): self
    {
        return new self($row['id'], $row['status']);
    }

    public function status(): string
    {
        return $this->status;
    }

    public function ship(): self
    {
        if ($this->status !== 'paid') {
            throw new \LogicException('Only paid orders can be shipped');
        }
        return new self($this->id, 'shipped');
    }

    /** @return array{id: string, status: string} */
    public function toArray(): array
    {
        return ['id' => $this->id, 'status' => $this->status];
    }
}
