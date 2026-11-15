<?php

declare(strict_types=1);

namespace Acme\ShopOrders\Tests\Acceptance;

use Acme\ShopOrders\Order;
use Acme\ShopOrders\OrderLabel;
use Acme\ShopOrders\OrderStatus;
use PHPUnit\Framework\TestCase;

final class OrderStatusTest extends TestCase
{
    public function testTheStatusIsABackedEnumWithTheStoredValues(): void
    {
        self::assertTrue(enum_exists(OrderStatus::class));
        // The order of the cases is not part of the task.
        self::assertEqualsCanonicalizing(
            ['pending', 'paid', 'shipped'],
            array_map(static fn (OrderStatus $s): string => $s->value, OrderStatus::cases()),
        );
    }

    public function testRowsAreReadIntoTheEnum(): void
    {
        $order = Order::fromRow(['id' => '7', 'status' => 'paid']);
        self::assertSame(OrderStatus::from('paid'), $order->status());
        self::assertSame(OrderStatus::from('shipped'), $order->ship()->status());
    }

    public function testTheApiStillReceivesStrings(): void
    {
        $data = Order::fromRow(['id' => '7', 'status' => 'paid'])->toArray();
        self::assertSame(['id' => '7', 'status' => 'paid'], $data);
        self::assertSame('{"id":"7","status":"paid"}', json_encode($data));
    }

    public function testUnknownStoredStatusIsRejected(): void
    {
        $this->expectException(\Throwable::class);
        Order::fromRow(['id' => '7', 'status' => 'refunded']);
    }

    public function testOnlyPaidOrdersShip(): void
    {
        $this->expectException(\LogicException::class);
        Order::fromRow(['id' => '7', 'status' => 'pending'])->ship();
    }

    public function testLabelsTakeTheEnum(): void
    {
        self::assertSame('Awaiting payment', (new OrderLabel())->label(OrderStatus::from('pending')));
        self::assertSame('Shipped', (new OrderLabel())->label(OrderStatus::from('shipped')));
    }
}
