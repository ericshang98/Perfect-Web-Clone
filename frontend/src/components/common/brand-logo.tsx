'use client';

import Image from 'next/image';
import Link from 'next/link';
import { Brand } from '@/types/landing';

export function BrandLogo({ brand }: { brand: Brand }) {
  const isSvg = brand.logo?.src.endsWith('.svg');
  const logoSrc = brand.logo?.src || '';
  const hasThemeVariants = logoSrc === '/logo.svg';

  return (
    <Link
      href={brand.url || '/'}
      target={brand.target || '_self'}
      className={`flex items-center space-x-3 ${brand.className || ''}`}
    >
      {brand.logo && (
        hasThemeVariants ? (
          <>
            {/* Light mode logo */}
            <Image
              src="/logo-for-light.svg"
              alt={brand.title ? '' : brand.logo.alt || ''}
              width={brand.logo.width || 80}
              height={brand.logo.height || 80}
              className="h-10 w-auto dark:hidden"
              unoptimized
            />
            {/* Dark mode logo */}
            <Image
              src="/logo-for-dark.svg"
              alt={brand.title ? '' : brand.logo.alt || ''}
              width={brand.logo.width || 80}
              height={brand.logo.height || 80}
              className="h-10 w-auto hidden dark:block"
              unoptimized
            />
          </>
        ) : (
          <Image
            src={brand.logo.src}
            alt={brand.title ? '' : brand.logo.alt || ''}
            width={brand.logo.width || 80}
            height={brand.logo.height || 80}
            className={isSvg ? "h-10 w-auto" : "h-8 w-auto rounded-lg"}
            unoptimized={brand.logo.src.startsWith('http') || isSvg}
          />
        )
      )}
      {brand.title && (
        <span className="text-lg font-medium">{brand.title}</span>
      )}
    </Link>
  );
}
