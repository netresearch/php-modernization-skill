<?php

declare(strict_types=1);

namespace Cases\EnumOrderStatus;

final class Order
{
    private OrderStatus $status;

    public function __construct(private string $id, OrderStatus|string $status)
    {
        if (is_string($status)) {
            $status = OrderStatus::tryFrom($status)
                ?? throw new \InvalidArgumentException('Unknown order status: ' . $status);
        }
        $this->status = $status;
    }

    /** @param array{id: string, status: string} $row */
    public static function fromRow(array $row): self
    {
        return new self($row['id'], $row['status']);
    }

    public function status(): OrderStatus
    {
        return $this->status;
    }

    public function ship(): self
    {
        if ($this->status !== OrderStatus::PAID) {
            throw new \LogicException('Only paid orders can be shipped');
        }
        return new self($this->id, OrderStatus::SHIPPED);
    }

    /** @return array{id: string, status: string} */
    public function toArray(): array
    {
        return ['id' => $this->id, 'status' => $this->status->value];
    }
}
