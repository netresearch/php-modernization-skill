<?php

declare(strict_types=1);

namespace Acme\Payments;

enum PaymentMethod: string
{
    case Card = 'card';
    case Invoice = 'invoice';
    case Paypal = 'paypal';
}
