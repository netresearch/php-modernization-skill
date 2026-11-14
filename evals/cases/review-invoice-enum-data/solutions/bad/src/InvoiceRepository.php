<?php

declare(strict_types=1);

namespace Cases\ReviewInvoiceEnumData;

final class InvoiceRepository
{
    public function __construct(private string $file = __DIR__ . '/../data/invoices.json')
    {
    }

    /** @return list<Invoice> */
    public function all(): array
    {
        /** @var list<array{id: string, status: string, total: int}> $rows */
        $rows = json_decode((string) file_get_contents($this->file), true, 512, JSON_THROW_ON_ERROR);

        return array_map(
            static fn (array $row): Invoice => new Invoice($row['id'], InvoiceStatus::from($row['status']), $row['total']),
            $rows,
        );
    }
}
