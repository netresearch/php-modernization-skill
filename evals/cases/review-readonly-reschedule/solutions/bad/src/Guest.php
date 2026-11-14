<?php

declare(strict_types=1);

namespace Cases\ReviewReadonlyReschedule;

final readonly class Guest
{
    public function __construct(private string $name, private string $email)
    {
    }

    public function name(): string
    {
        return $this->name;
    }

    public function email(): string
    {
        return $this->email;
    }
}
