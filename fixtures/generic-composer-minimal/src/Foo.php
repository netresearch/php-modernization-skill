<?php

declare(strict_types=1);

namespace Fixtures\GenericComposerMinimal;

final class Foo
{
    public function greet(string $name): string
    {
        return 'Hello, ' . $name;
    }
}
