<?php

declare(strict_types=1);

namespace Cases\EnumOrderStatus;

final class Order
{
    public function __construct(private string $id, private OrderStatus $status)
    {
    }

    /** @param array{id: string, status: string} $row */
    public static function fromRow(array $row): self
    {
        return new self($row['id'], OrderStatus::from($row['status']));
    }

    public function status(): OrderStatus
    {
        return $this->status;
    }

    public function ship(): self
    {
        if ($this->status !== OrderStatus::Paid) {
            throw new \LogicException('Only paid orders can be shipped');
        }
        return new self($this->id, OrderStatus::Shipped);
    }

    /** @return array{id: string, status: OrderStatus} */
    public function toArray(): array
    {
        return ['id' => $this->id, 'status' => $this->status];
    }
}
