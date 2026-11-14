<?php

declare(strict_types=1);

namespace Cases\ReviewInvoiceEnumData\Tests\Acceptance;

use Cases\ReviewInvoiceEnumData\InvoiceLabel;
use Cases\ReviewInvoiceEnumData\InvoiceRepository;
use PHPUnit\Framework\TestCase;

final class InvoiceTest extends TestCase
{
    public function testTheEnumHasTheStoredValues(): void
    {
        $enum = 'Cases\\ReviewInvoiceEnumData\\InvoiceStatus';
        self::assertTrue(enum_exists($enum));
        self::assertSame(['open', 'paid'], array_map(static fn ($c) => $c->value, $enum::cases()));
    }

    public function testEveryStoredInvoiceLoads(): void
    {
        $invoices = (new InvoiceRepository())->all();
        self::assertCount(3, $invoices);
        self::assertSame('open', $invoices[0]->status()?->value);
    }

    public function testUnknownStoredStatusShowsUnknown(): void
    {
        $invoices = (new InvoiceRepository())->all();
        $labels = array_map(static fn ($i) => (new InvoiceLabel())->label($i->status()), $invoices);
        self::assertSame(['Open', 'Paid', 'Unknown'], $labels);
    }
}
